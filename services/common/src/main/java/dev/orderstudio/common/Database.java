package dev.orderstudio.common;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.*;
import java.util.*;

/** Short SQLite transactions; HTTP calls must happen outside this boundary. */
public final class Database {
  private final String url;

  public Database(String path) {
    try {
      Files.createDirectories(Path.of(path).toAbsolutePath().getParent());
    } catch (Exception e) {
      throw new IllegalStateException("Cannot create database directory", e);
    }
    url = "jdbc:sqlite:" + path;
  }

  @FunctionalInterface
  public interface Work<T> {
    T run(Connection c) throws SQLException;
  }

  public Connection open() throws SQLException {
    Connection c = DriverManager.getConnection(url);
    try {
      update(c, "PRAGMA busy_timeout=5000");
      return c;
    } catch (SQLException e) {
      c.close();
      throw e;
    }
  }

  public <T> T read(Work<T> work) {
    return transaction(false, work);
  }

  public <T> T write(Work<T> work) {
    return transaction(true, work);
  }

  private <T> T transaction(boolean write, Work<T> work) {
    try (Connection c = open()) {
      update(c, write ? "BEGIN IMMEDIATE" : "BEGIN");
      try {
        T result = work.run(c);
        update(c, "COMMIT");
        return result;
      } catch (SQLException | RuntimeException e) {
        try {
          update(c, "ROLLBACK");
        } catch (SQLException rollback) {
          e.addSuppressed(rollback);
        }
        throw e;
      }
    } catch (SQLException e) {
      throw new StorageException(e);
    }
  }

  public void initialize(String... statements) {
    try (Connection c = open()) {
      update(c, "PRAGMA journal_mode=WAL");
    } catch (SQLException e) {
      throw new StorageException(e);
    }
    write(
        c -> {
          for (String sql : statements) update(c, sql);
          return null;
        });
  }

  public static int update(Connection c, String sql, Object... values) throws SQLException {
    try (PreparedStatement p = c.prepareStatement(sql)) {
      bind(p, values);
      p.execute();
      return p.getUpdateCount();
    }
  }

  public static List<Map<String, Object>> rows(Connection c, String sql, Object... values)
      throws SQLException {
    try (PreparedStatement p = c.prepareStatement(sql)) {
      bind(p, values);
      try (ResultSet rs = p.executeQuery()) {
        List<Map<String, Object>> result = new ArrayList<>();
        while (rs.next()) {
          Map<String, Object> row = new LinkedHashMap<>();
          for (int i = 1; i <= rs.getMetaData().getColumnCount(); i++)
            row.put(rs.getMetaData().getColumnLabel(i), rs.getObject(i));
          result.add(row);
        }
        return result;
      }
    }
  }

  public static Map<String, Object> one(Connection c, String sql, Object... values)
      throws SQLException {
    var results = rows(c, sql, values);
    return results.isEmpty() ? null : results.getFirst();
  }

  private static void bind(PreparedStatement p, Object[] values) throws SQLException {
    for (int i = 0; i < values.length; i++) p.setObject(i + 1, values[i]);
  }

  public static final class StorageException extends RuntimeException {
    public StorageException(Throwable cause) {
      super("Storage unavailable", cause);
    }
  }
}
